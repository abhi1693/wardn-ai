import asyncio
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.agents import chat_orchestrator, provider_clients, service, skills, tool_execution
from app.modules.agents.models import (
    Agent,
    AgentMCPServerAssignment,
    AgentRun,
    AgentRunStep,
    ConversationMessage,
    WorkspaceApprovedSkill,
    WorkspaceConversation,
)
from app.modules.agents.schemas import (
    AgentChatMessage,
    AgentChatRequest,
    AgentSkillUpdateRequest,
    WorkspaceAgentModelUpdate,
    WorkspaceSkillAgentAssignmentRequest,
    WorkspaceSkillApproveRequest,
)
from app.modules.agents.types import AgentRuntimeTool, AgentRuntimeToolGuardrailFilter
from app.modules.guardrails.service import GuardrailDecision
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.schemas import LLMProviderModelListResponse, LLMProviderModelRead
from app.modules.llm_providers.service import ResolvedLLMCredentialSecrets
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.users.models import User
from tests.database_fakes import EmptyResult


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

    async def execute(self, *args, **kwargs) -> EmptyResult:
        return EmptyResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def begin(self):
        return FakeTransaction(self)


@pytest.mark.asyncio
async def test_agent_quota_locks_are_acquired_before_counts(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com")
    events: list[str] = []
    captured_scopes = []

    async def lock_quota_capacity(session, scopes):
        events.append("lock")
        captured_scopes.extend(scopes)

    async def count_organization(*args, **kwargs):
        events.append("organization_count")
        return 0

    async def count_workspace(*args, **kwargs):
        events.append("workspace_count")
        return 0

    async def count_user(*args, **kwargs):
        events.append("user_count")
        return 0

    async def require_limit_available(*args, **kwargs):
        return None

    monkeypatch.setattr(service.limits_service, "lock_quota_capacity", lock_quota_capacity)
    monkeypatch.setattr(
        service.repository,
        "count_active_agents_for_organization",
        count_organization,
    )
    monkeypatch.setattr(
        service.repository,
        "count_active_agents_for_workspace",
        count_workspace,
    )
    monkeypatch.setattr(
        service.repository,
        "count_active_agents_created_by_user_for_workspace",
        count_user,
    )
    monkeypatch.setattr(
        service.limits_service,
        "require_limit_available",
        require_limit_available,
    )

    await service.require_agent_create_limit(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
    )

    assert events == ["lock", "organization_count", "workspace_count", "user_count"]
    assert {scope.limit_key for scope in captured_scopes} == {
        service.limits_service.AGENTS_PER_ORGANIZATION,
        service.limits_service.AGENTS_PER_WORKSPACE,
        service.limits_service.AGENTS_PER_WORKSPACE_PER_USER,
    }


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


def make_agent_runtime_tool(
    *,
    wire_name: str,
    tool_name: str,
    config_name: str = "default",
    title: str | None = None,
    description: str = "",
    input_schema: dict | None = None,
    annotations: dict | None = None,
    workspace_id=None,
    organization_id=None,
    server_name: str = "io.github.example/tools",
) -> AgentRuntimeTool:
    workspace_id = workspace_id or uuid4()
    organization_id = organization_id or uuid4()
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name=server_name,
        config_name=config_name,
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version=installation.installed_version,
        description="Example MCP server",
        server_json={},
        packages=[],
        remotes=[],
        icons=[],
        is_latest=True,
        status="active",
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        tool_name=tool_name,
        title=title or tool_name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
        annotations=annotations or {},
        is_active=True,
    )
    return AgentRuntimeTool(
        wire_name=wire_name,
        assignment_id=uuid4(),
        tool_schema=tool_schema,
        installation=installation,
        server=server,
    )


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


def chat_message(role: str, content: str) -> AgentChatMessage:
    return AgentChatMessage(role=role, parts=[{"type": "text", "text": content}])


def persisted_conversation_message(
    conversation_id,
    *,
    role: str,
    content: str,
    sequence: int,
) -> ConversationMessage:
    return ConversationMessage(
        id=uuid4(),
        conversation_id=conversation_id,
        role=role,
        content=content,
        parts=[{"type": "text", "text": content}],
        sequence=sequence,
    )


def persisted_compaction_message(
    conversation_id,
    *,
    content: str,
    sequence: int,
) -> ConversationMessage:
    return ConversationMessage(
        id=uuid4(),
        conversation_id=conversation_id,
        role="system",
        content=content,
        parts=[
            {"type": service.CHAT_COMPACTION_PART_TYPE, "data": {"messageCount": sequence - 1}},
            {"type": "text", "text": content},
        ],
        sequence=sequence,
    )


def test_conversation_chat_context_messages_replays_latest_compaction_only() -> None:
    conversation_id = uuid4()
    messages = [
        persisted_conversation_message(
            conversation_id,
            role="user",
            content="Old user detail",
            sequence=1,
        ),
        persisted_conversation_message(
            conversation_id,
            role="assistant",
            content="Old assistant detail",
            sequence=2,
        ),
        persisted_compaction_message(
            conversation_id,
            content="Project Apollo is the active project.",
            sequence=3,
        ),
        persisted_conversation_message(
            conversation_id,
            role="assistant",
            content="Compacted this chat.",
            sequence=4,
        ),
    ]

    context, incoming_tail = service.conversation_chat_context_messages(
        messages,
        [
            chat_message("user", "Old user detail"),
            chat_message("assistant", "Old assistant detail"),
            chat_message("assistant", "Compacted this chat."),
            chat_message("user", "What project is active?"),
        ],
    )

    assert incoming_tail == [chat_message("user", "What project is active?")]
    assert [
        (message.role, service.text_from_chat_message(message))
        for message in context
    ] == [
        ("assistant", "Earlier conversation summary:\nProject Apollo is the active project."),
        ("assistant", "Compacted this chat."),
        ("user", "What project is active?"),
    ]


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
async def test_persisted_agent_chat_stream_persists_tool_progress_steps(
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
    steps: list[dict] = []
    finished: list[dict] = []

    async def append_agent_run_step(*args, **kwargs):
        steps.append(kwargs)

    async def append_conversation_message(*args, **kwargs):
        return None

    async def finish_agent_run(*args, **kwargs):
        finished.append(kwargs)

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def provider_stream():
        yield service.AgentChatToolActivityEvent(
            id="tool-call-1",
            tool_name="gsc_sites",
            status="running",
            message="Waiting for runtime result.",
            progress_token="agent-tool:call-1",
        )
        yield service.AgentChatTextEvent(text="Done")

    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        service.repository,
        "append_conversation_message",
        append_conversation_message,
    )
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)

    chunks = ui_stream_chunks(
        [
            chunk
            async for chunk in service.persisted_agent_chat_stream(
                conversation,
                provider_stream(),
                agent_run,
                session_factory=fake_session_factory(FakeSession()),
            )
        ]
    )

    assert any(chunk["type"] == "data-tool-activity" for chunk in chunks)
    assert steps[0]["step_type"] == "tool_progress"
    assert steps[0]["status"] == "running"
    assert steps[0]["title"] == "gsc_sites"
    assert steps[0]["payload"]["message"] == "Waiting for runtime result."
    assert steps[0]["payload"]["progressToken"] == "[redacted]"
    assert steps[-1]["step_type"] == "model_output"
    assert finished == [{"status": "succeeded", "error": ""}]


@pytest.mark.asyncio
async def test_persisted_agent_chat_stream_emits_reasoning_summary_parts(
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
        yield service.AgentChatReasoningSummaryEvent(
            summary="Checked the available tool result before answering."
        )
        yield service.AgentChatReasoningSummaryEvent(
            summary="Checked the available tool result before answering."
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
        "data-reasoning-summary",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert chunks[1]["data"] == {
        "summary": "Checked the available tool result before answering."
    }
    assert persisted[0]["parts"][0]["type"] == "data-reasoning-summary"
    assert persisted[0]["parts"][0]["data"] == {
        "summary": "Checked the available tool result before answering."
    }
    assert persisted[0]["parts"][1] == {"type": "text", "text": "Final answer"}
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
async def test_persisted_agent_chat_stream_finishes_when_final_persistence_fails(
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

    async def append_conversation_message(*args, **kwargs):
        raise RuntimeError("conversation write failed")

    async def provider_stream():
        yield service.AgentChatTextEvent(text="Final answer")

    monkeypatch.setattr(
        service.repository,
        "append_conversation_message",
        append_conversation_message,
    )

    chunks = ui_stream_chunks(
        [
            chunk
            async for chunk in service.persisted_agent_chat_stream(
                conversation,
                provider_stream(),
                session_factory=fake_session_factory(FakeSession()),
            )
        ]
    )

    assert chunks[-1] == {"type": "finish", "finishReason": "error"}
    assert [chunk["type"] for chunk in chunks] == [
        "start",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert chunks[2]["delta"] == "Final answer"
    assert "conversation write failed" in chunks[3]["delta"]


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

    async def get_workspace_conversation(*args, **kwargs):
        raise AssertionError("client-generated chat ids must not be loaded as conversations")

    async def refresh_wildcard_agent_server_tools(*args, **kwargs):
        return None

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        return []

    async def filter_agent_runtime_tools_for_guardrails(*args, **kwargs):
        return AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={})

    async def run_agent_chat(*args, **kwargs):
        seen_provider_run.append(kwargs["agent_run"])
        yield service.AgentChatTextEvent(text="ok")

    monkeypatch.setattr(service, "get_agent_model_for_run", get_agent_model_for_run)
    monkeypatch.setattr(service.repository, "create_agent_run", create_agent_run)
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)
    monkeypatch.setattr(
        service.repository,
        "get_workspace_conversation",
        get_workspace_conversation,
    )
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
            id="client-chat-13adec9fa6e64ffe9bb9e4f865b1a4eb",
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
async def test_stream_agent_chat_syncs_workspace_tools_before_runtime_discovery(
    monkeypatch,
) -> None:
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
        trigger_type="scheduled",
        status="running",
    )
    enabled_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.github/github-mcp-server",
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
    events: list[str] = []

    async def get_agent_model_for_run(*args, **kwargs):
        return agent, credential

    async def create_agent_run(*args, **kwargs):
        return agent_run

    async def append_agent_run_step(*args, **kwargs):
        return None

    async def finish_agent_run(*args, **kwargs):
        return None

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def get_workspace_conversation(*args, **kwargs):
        raise AssertionError("client-generated chat ids must not be loaded as conversations")

    async def list_installations(*args, **kwargs):
        events.append("list_installations")
        assert kwargs["workspace_id"] == workspace_id
        return [disabled_installation, enabled_installation]

    async def replace_agent_tools(*args, **kwargs):
        events.append("replace_agent_tools")
        assert kwargs["agent_id"] == agent.id
        assert kwargs["server_assignments"] == [(enabled_installation, True, [])]

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        events.append("list_runtime_tools")
        assert "replace_agent_tools" in events
        return []

    async def refresh_wildcard_agent_server_tools(*args, **kwargs):
        return []

    async def filter_agent_runtime_tools_for_guardrails(*args, **kwargs):
        return AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={})

    async def run_agent_chat(*args, **kwargs):
        yield service.AgentChatTextEvent(text="ok")

    monkeypatch.setattr(service, "get_agent_model_for_run", get_agent_model_for_run)
    monkeypatch.setattr(service.repository, "create_agent_run", create_agent_run)
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)
    monkeypatch.setattr(
        service.repository,
        "get_workspace_conversation",
        get_workspace_conversation,
    )
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(
        service.repository,
        "list_agent_tool_runtime_rows",
        list_agent_tool_runtime_rows,
    )
    monkeypatch.setattr(
        service,
        "refresh_wildcard_agent_server_tools",
        refresh_wildcard_agent_server_tools,
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
            id="client-chat-scheduled",
            messages=[
                AgentChatMessage(role="user", parts=[{"type": "text", "text": "review PRs"}])
            ],
        ),
        workspace_id=workspace_id,
        session_factory=fake_session_factory(FakeSession()),
        trigger_type="scheduled",
    )
    chunks = ui_stream_chunks([chunk async for chunk in stream])

    assert events[:3] == ["list_installations", "replace_agent_tools", "list_runtime_tools"]
    assert chunks[-1] == {"type": "finish", "finishReason": "stop"}


async def run_existing_conversation_chat_with_history(
    monkeypatch,
    *,
    incoming_messages: list[AgentChatMessage],
    trigger_type: str = "chat",
):
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
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        created_by_id=user.id,
        title="Chat",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        trigger_type=trigger_type,
        status="running",
    )
    persisted_messages = [
        persisted_conversation_message(
            conversation.id,
            role="user",
            content="Remember project Apollo.",
            sequence=1,
        ),
        persisted_conversation_message(
            conversation.id,
            role="assistant",
            content="Got it.",
            sequence=2,
        ),
    ]
    seen_model_messages: list[list[tuple[str, str]]] = []
    persisted_writes: list[dict] = []
    steps: list[dict] = []

    async def get_agent_model_for_run(*args, **kwargs):
        return agent, credential

    async def get_workspace_conversation(*args, **kwargs):
        return conversation

    async def list_conversation_messages(*args, **kwargs):
        return persisted_messages

    async def create_agent_run(*args, **kwargs):
        return agent_run

    async def append_agent_run_step(*args, **kwargs):
        steps.append(kwargs)

    async def append_conversation_message(*args, **kwargs):
        persisted_writes.append(kwargs)

    async def finish_agent_run(*args, **kwargs):
        return None

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def refresh_wildcard_agent_server_tools(*args, **kwargs):
        return []

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        return []

    async def filter_agent_runtime_tools_for_guardrails(*args, **kwargs):
        return AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={})

    async def run_agent_chat(*args, **kwargs):
        payload = args[2]
        seen_model_messages.append(
            [
                (message.role, service.text_from_chat_message(message))
                for message in payload.messages
            ]
        )
        yield service.AgentChatTextEvent(text="Apollo was the project.")

    monkeypatch.setattr(service, "get_agent_model_for_run", get_agent_model_for_run)
    monkeypatch.setattr(
        service.repository,
        "get_workspace_conversation",
        get_workspace_conversation,
    )
    monkeypatch.setattr(
        service.repository,
        "list_conversation_messages",
        list_conversation_messages,
    )
    monkeypatch.setattr(service.repository, "create_agent_run", create_agent_run)
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        service.repository,
        "append_conversation_message",
        append_conversation_message,
    )
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
            id=str(conversation.id),
            messages=incoming_messages,
        ),
        workspace_id=workspace_id,
        session_factory=fake_session_factory(FakeSession()),
        trigger_type=trigger_type,
    )
    chunks = ui_stream_chunks([chunk async for chunk in stream])

    return SimpleNamespace(
        agent_run=agent_run,
        chunks=chunks,
        persisted_writes=persisted_writes,
        seen_model_messages=seen_model_messages,
        steps=steps,
    )


@pytest.mark.asyncio
async def test_stream_agent_chat_includes_persisted_history_for_current_turn_payload(
    monkeypatch,
) -> None:
    result = await run_existing_conversation_chat_with_history(
        monkeypatch,
        incoming_messages=[chat_message("user", "What project did I mention?")],
        trigger_type="whatsapp",
    )

    assert result.seen_model_messages == [
        [
            ("user", "Remember project Apollo."),
            ("assistant", "Got it."),
            ("user", "What project did I mention?"),
        ]
    ]
    assert result.persisted_writes[0]["role"] == "user"
    assert result.persisted_writes[0]["content"] == "What project did I mention?"
    assert result.persisted_writes[0]["agent_run_id"] == result.agent_run.id
    assert result.persisted_writes[1]["role"] == "assistant"
    assert result.steps[0]["payload"] == {
        "message": "What project did I mention?",
        "messageCount": 3,
    }
    assert result.chunks[-1] == {"type": "finish", "finishReason": "stop"}


@pytest.mark.asyncio
async def test_stream_agent_chat_deduplicates_full_history_payload_for_builtin_chat(
    monkeypatch,
) -> None:
    result = await run_existing_conversation_chat_with_history(
        monkeypatch,
        incoming_messages=[
            chat_message("user", "Remember project Apollo."),
            chat_message("assistant", "Got it."),
            chat_message("user", "What project did I mention?"),
        ],
    )

    assert result.seen_model_messages == [
        [
            ("user", "Remember project Apollo."),
            ("assistant", "Got it."),
            ("user", "What project did I mention?"),
        ]
    ]
    assert result.persisted_writes[0]["role"] == "user"
    assert result.persisted_writes[0]["content"] == "What project did I mention?"
    assert result.persisted_writes[1]["role"] == "assistant"
    assert result.chunks[-1] == {"type": "finish", "finishReason": "stop"}


@pytest.mark.asyncio
async def test_stream_agent_chat_compact_command_appends_hidden_summary(
    monkeypatch,
) -> None:
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
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        created_by_id=user.id,
        title="Chat",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        trigger_type="chat",
        status="running",
    )
    persisted_messages = [
        persisted_conversation_message(
            conversation.id,
            role="user",
            content="Remember project Apollo.",
            sequence=1,
        ),
        persisted_conversation_message(
            conversation.id,
            role="assistant",
            content="Got it.",
            sequence=2,
        ),
    ]
    persisted_writes: list[dict] = []

    async def require_workspace_member(*args, **kwargs):
        return None, None, None

    async def get_agent_model_for_run(*args, **kwargs):
        return agent, credential

    async def get_workspace_conversation(*args, **kwargs):
        return conversation

    async def list_conversation_messages(*args, **kwargs):
        return persisted_messages

    async def create_agent_run(*args, **kwargs):
        return agent_run

    async def append_agent_run_step(*args, **kwargs):
        return None

    async def append_conversation_message(*args, **kwargs):
        persisted_writes.append(kwargs)
        message = persisted_conversation_message(
            kwargs["conversation_id"],
            role=kwargs["role"],
            content=kwargs["content"],
            sequence=len(persisted_messages) + 1,
        )
        message.parts = kwargs["parts"]
        message.agent_run_id = kwargs.get("agent_run_id")
        persisted_messages.append(message)
        return message

    async def finish_agent_run(*args, **kwargs):
        return None

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def run_agent_chat(*args, **kwargs):
        raise AssertionError("/compact should not call the model")
        yield service.AgentChatTextEvent(text="unreachable")

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service, "get_agent_model_for_run", get_agent_model_for_run)
    monkeypatch.setattr(
        service.repository,
        "get_workspace_conversation",
        get_workspace_conversation,
    )
    monkeypatch.setattr(
        service.repository,
        "list_conversation_messages",
        list_conversation_messages,
    )
    monkeypatch.setattr(service.repository, "create_agent_run", create_agent_run)
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        service.repository,
        "append_conversation_message",
        append_conversation_message,
    )
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)
    monkeypatch.setattr(service, "run_agent_chat", run_agent_chat)

    stream = await service.stream_agent_chat(
        FakeSession(),
        user,
        organization_id,
        agent.id,
        AgentChatRequest(
            id=str(conversation.id),
            messages=[chat_message("user", "/compact")],
        ),
        workspace_id=workspace_id,
        session_factory=fake_session_factory(FakeSession()),
    )
    chunks = ui_stream_chunks([chunk async for chunk in stream])

    assert [write["role"] for write in persisted_writes] == ["user", "system", "assistant"]
    assert persisted_writes[1]["parts"][0]["type"] == service.CHAT_COMPACTION_PART_TYPE
    assert "Remember project Apollo" in persisted_writes[1]["content"]
    assert any(
        chunk.get("type") == "text-delta" and "Compacted this chat" in chunk["delta"]
        for chunk in chunks
    )
    assert chunks[-1] == {"type": "finish", "finishReason": "stop"}


@pytest.mark.asyncio
async def test_list_workspace_agent_runs_includes_usage_and_provider_trigger(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    conversation_id = uuid4()
    run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=uuid4(),
        conversation_id=conversation_id,
        triggered_by_id=uuid4(),
        trigger_type="chat",
        status="succeeded",
        started_at=datetime(2026, 8, 2, 19, 43, tzinfo=UTC),
        finished_at=datetime(2026, 8, 2, 19, 44, tzinfo=UTC),
        error="",
        created_at=datetime(2026, 8, 2, 19, 43, tzinfo=UTC),
        updated_at=datetime(2026, 8, 2, 19, 44, tzinfo=UTC),
    )
    usage = SimpleNamespace(
        input_tokens=123,
        output_tokens=45,
        total_tokens=168,
        cost_usd="0.00042",
        tool_calls=3,
    )

    async def require_workspace_member(*args, **kwargs):
        return None

    async def list_agent_runs(*args, **kwargs):
        return [run]

    async def agent_run_usage_summaries(*args, **kwargs):
        return {run.id: usage}

    async def list_chat_provider_triggers_by_conversation(*args, **kwargs):
        return {conversation_id: "whatsapp_local"}

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service.repository, "list_agent_runs", list_agent_runs)
    monkeypatch.setattr(
        service.observability_service,
        "agent_run_usage_summaries",
        agent_run_usage_summaries,
    )
    monkeypatch.setattr(
        service.repository,
        "list_chat_provider_triggers_by_conversation",
        list_chat_provider_triggers_by_conversation,
    )

    response = await service.list_workspace_agent_runs(
        FakeSession(),
        User(id=uuid4(), email="owner@example.com"),
        organization_id,
        workspace_id,
    )

    assert len(response.runs) == 1
    assert response.runs[0].trigger_type == "whatsapp"
    assert response.runs[0].input_tokens == 123
    assert response.runs[0].output_tokens == 45
    assert response.runs[0].total_tokens == 168
    assert response.runs[0].tool_calls == 3


def test_conversation_id_from_payload_only_accepts_canonical_wardn_uuids() -> None:
    conversation_id = uuid4()

    assert (
        service.conversation_id_from_payload(
            AgentChatRequest(id=str(conversation_id), messages=[])
        )
        == conversation_id
    )
    assert (
        service.conversation_id_from_payload(
            AgentChatRequest(id=conversation_id.hex, messages=[])
        )
        is None
    )
    assert (
        service.conversation_id_from_payload(
            AgentChatRequest(id="client-chat-13adec9fa6e64ffe9bb9e4f865b1a4eb", messages=[])
        )
        is None
    )


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
        skill_ids=[skills.WARDN_FIND_SKILLS_ID],
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

    monkeypatch.setattr(
        chat_orchestrator,
        "resolve_credential_secrets",
        resolve_credential_secrets,
    )
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(
        chat_orchestrator,
        "refresh_chatgpt_oauth_credential",
        refresh_chatgpt_oauth_credential,
    )
    monkeypatch.setattr(
        chat_orchestrator,
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
        "allowed": AgentRuntimeTool(
            wire_name="allowed",
            assignment_id=uuid4(),
            tool_schema=allowed_schema,
            installation=installation,
            server=server,
        ),
        "denied": AgentRuntimeTool(
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
        chat_orchestrator,
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
    guardrail_filter = AgentRuntimeToolGuardrailFilter(
        allowed_tools={},
        denied_tools={
            "search": (
                AgentRuntimeTool(
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


def test_denied_mcp_request_preflight_skips_when_any_tool_is_allowed() -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    installation_id = uuid4()
    installation = MCPServerInstallation(
        id=installation_id,
        workspace_id=workspace_id,
        server_name="io.github.AIops-tools/k8s-aiops",
        config_name="rancher-qa-omsllc",
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
        description="Kubernetes tools",
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
        installation_id=installation_id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="namespace_list",
        title="namespace_list",
        description="[READ] List namespaces.",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    denied_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="api_resources",
        title="api_resources",
        description="[READ] List available API groups and their versions.",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    guardrail_filter = AgentRuntimeToolGuardrailFilter(
        allowed_tools={
            "allowed": AgentRuntimeTool(
                wire_name="allowed",
                assignment_id=uuid4(),
                tool_schema=allowed_schema,
                installation=installation,
                server=server,
            )
        },
        denied_tools={
            "denied": (
                AgentRuntimeTool(
                    wire_name="denied",
                    assignment_id=uuid4(),
                    tool_schema=denied_schema,
                    installation=installation,
                    server=server,
                ),
                GuardrailDecision(
                    mode="deny",
                    message=(
                        "Tool call blocked because it did not match any active allow "
                        "guardrail policy."
                    ),
                ),
            )
        },
    )

    assert not service.message_requests_denied_mcp_tool(
        AgentChatMessage(
            role="user",
            parts=[{"type": "text", "text": "list all namespaces from omsllc cluster"}],
        ),
        guardrail_filter,
    )
    assert not service.message_requests_denied_mcp_tool(
        AgentChatMessage(
            role="user",
            parts=[{"type": "text", "text": "read my latest emails"}],
        ),
        guardrail_filter,
    )


def test_denied_mcp_request_preflight_blocks_matching_denied_tool_with_allowed_tools() -> None:
    allowed_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        server_name="io.github.AIops-tools/k8s-aiops",
        title="List namespaces",
        description="[READ] List Kubernetes namespaces.",
    )
    denied_tool = make_agent_runtime_tool(
        wire_name="wardn_gsc_sites",
        tool_name="gsc_sites",
        server_name="io.github.acamolese/google-search-console-mcp",
        title="List Search Console sites",
        description="[READ] List Google Search Console sites.",
    )
    guardrail_filter = AgentRuntimeToolGuardrailFilter(
        allowed_tools={allowed_tool.wire_name: allowed_tool},
        denied_tools={
            denied_tool.wire_name: (
                denied_tool,
                GuardrailDecision(
                    mode="deny",
                    message=(
                        "Tool call blocked because it did not match any active allow "
                        "guardrail policy."
                    ),
                ),
            )
        },
    )
    message = AgentChatMessage(
        role="user",
        parts=[{"type": "text", "text": "check on shipyardhq.dev in gsc"}],
    )

    matches = service.denied_mcp_tool_matches(message, guardrail_filter)

    assert service.message_requests_denied_mcp_tool(message, guardrail_filter)
    assert matches[0][0] is denied_tool


@pytest.mark.asyncio
async def test_preflight_blocked_tool_stream_reports_matching_denied_tool() -> None:
    allowed_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        server_name="io.github.AIops-tools/k8s-aiops",
    )
    denied_tool = make_agent_runtime_tool(
        wire_name="wardn_gsc_sites",
        tool_name="gsc_sites",
        server_name="io.github.acamolese/google-search-console-mcp",
        title="List Search Console sites",
        description="[READ] List Google Search Console sites.",
    )
    denied_match = (
        denied_tool,
        GuardrailDecision(
            mode="deny",
            message="Tool call blocked because it did not match any active allow guardrail policy.",
        ),
    )
    guardrail_filter = AgentRuntimeToolGuardrailFilter(
        allowed_tools={allowed_tool.wire_name: allowed_tool},
        denied_tools={denied_tool.wire_name: denied_match},
    )

    events = [
        event
        async for event in service.preflight_blocked_tool_stream(
            guardrail_filter,
            denied_matches=[denied_match],
        )
    ]

    assert isinstance(events[0], service.AgentChatToolActivityEvent)
    assert events[0].tool_name == "gsc_sites"
    assert events[0].status == "blocked"
    assert isinstance(events[1], service.AgentChatTextEvent)
    assert "gsc_sites" in events[1].text


@pytest.mark.asyncio
async def test_stream_agent_chat_preflight_block_uses_cached_tools_before_refresh(
    monkeypatch,
) -> None:
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
    assignment = AgentMCPServerAssignment(
        id=uuid4(),
        agent_id=agent.id,
        installation_id=uuid4(),
    )
    installation = MCPServerInstallation(
        id=assignment.installation_id,
        workspace_id=workspace_id,
        server_name="io.github.AIops-tools/k8s-aiops",
        config_name="rancher-qa-omsllc",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version=installation.installed_version,
        description="Kubernetes tools",
        server_json={},
        packages=[],
        remotes=[],
        icons=[],
        is_latest=True,
        status="active",
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        tool_name="api_resources",
        title="API resources",
        description="Inspect Kubernetes API resources",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    steps: list[dict] = []
    finished: list[dict] = []

    async def get_agent_model_for_run(*args, **kwargs):
        return agent, credential

    async def create_agent_run(*args, **kwargs):
        return agent_run

    async def append_agent_run_step(*args, **kwargs):
        steps.append(kwargs)

    async def finish_agent_run(*args, **kwargs):
        finished.append(kwargs)

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        return [(assignment, tool_schema, installation, server)]

    async def filter_agent_runtime_tools_for_guardrails(*args, **kwargs):
        runtime_tools = args[1]
        tool = next(iter(runtime_tools.values()))
        return AgentRuntimeToolGuardrailFilter(
            allowed_tools={},
            denied_tools={
                tool.wire_name: (
                    tool,
                    GuardrailDecision(
                        mode="deny",
                        policy_name="default deny",
                        message=(
                            "Tool call blocked because it did not match any active allow "
                            "guardrail policy."
                        ),
                    ),
                )
            },
        )

    async def refresh_wildcard_agent_server_tools(*args, **kwargs):
        raise AssertionError("blocked preflight must not refresh MCP runtimes")

    async def run_agent_chat(*args, **kwargs):
        raise AssertionError("blocked preflight must not call the model")
        yield service.AgentChatTextEvent(text="unreachable")

    monkeypatch.setattr(service, "get_agent_model_for_run", get_agent_model_for_run)
    monkeypatch.setattr(service.repository, "create_agent_run", create_agent_run)
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)
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
    monkeypatch.setattr(
        service,
        "refresh_wildcard_agent_server_tools",
        refresh_wildcard_agent_server_tools,
    )
    monkeypatch.setattr(service, "run_agent_chat", run_agent_chat)

    stream = await service.stream_agent_chat(
        FakeSession(),
        user,
        organization_id,
        agent.id,
        AgentChatRequest(
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=[
                        {
                            "type": "text",
                            "text": "create an ns in rancher-qa omsllc with the name test-ns",
                        }
                    ],
                )
            ]
        ),
        workspace_id=workspace_id,
        session_factory=fake_session_factory(FakeSession()),
    )
    chunks = ui_stream_chunks([chunk async for chunk in stream])

    assert any(chunk.get("type") == "data-tool-activity" for chunk in chunks)
    assert any(
        chunk.get("type") == "text-delta"
        and "guardrail policies do not allow" in chunk.get("delta", "")
        for chunk in chunks
    )
    assert [step["step_type"] for step in steps] == [
        "model_input",
        "tool_result",
        "tool_result",
        "model_output",
    ]
    assert finished == [{"status": "succeeded", "error": ""}]


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


def test_reasoning_summaries_from_openai_event_reads_reasoning_output_items() -> None:
    assert service.reasoning_summaries_from_openai_event(
        {
            "type": "response.output_item.done",
            "item": {
                "type": "reasoning",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": " Checked the tool output before answering. ",
                    }
                ],
            },
        }
    ) == ["Checked the tool output before answering."]
    assert service.reasoning_summaries_from_openai_event(
        {
            "type": "response.completed",
            "response": {
                "output": [
                    {"type": "message", "content": []},
                    {
                        "type": "reasoning",
                        "summary": [
                            {
                                "type": "summary_text",
                                "text": "Compared the namespace target with the request.",
                            }
                        ],
                    },
                ]
            },
        }
    ) == ["Compared the namespace target with the request."]


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

    async def stream_response_events(*args, **kwargs):
        external_transaction_states.append(
            [session.in_transaction for session in session_factory.sessions]
        )
        yield {"type": "response.output_text.delta", "delta": "ok"}
        yield {
            "type": "response.completed",
            "response": {
                "id": "resp_1",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        }

    monkeypatch.setattr(
        chat_orchestrator,
        "resolve_credential_secrets",
        resolve_credential_secrets,
    )
    monkeypatch.setattr(
        service,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)
    monkeypatch.setattr(chat_orchestrator, "stream_response_events", stream_response_events)

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
    assert external_transaction_states
    assert all(
        not in_transaction
        for transaction_states in external_transaction_states
        for in_transaction in transaction_states
    )
    assert len(session_factory.sessions) >= 4
    assert all(not session.in_transaction for session in session_factory.sessions)
    assert sum(session.commits for session in session_factory.sessions) >= 4


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

    async def stream_response_events(*args, **kwargs):
        yield {"type": "response.output_text.delta", "delta": "ok"}
        yield {
            "type": "response.completed",
            "response": {
                "id": "resp_1",
                "model": "gpt-4o-mini-2024-07-18",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            },
        }

    async def record_agent_llm_usage(*args, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        chat_orchestrator,
        "resolve_credential_secrets",
        resolve_credential_secrets,
    )
    monkeypatch.setattr(chat_orchestrator, "stream_response_events", stream_response_events)
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)

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
        "reasoning": {"summary": "auto"},
        "stream": True,
        "include": [],
    }


def test_reasoning_request_for_model_only_enables_known_reasoning_models() -> None:
    assert service.reasoning_request_for_model("gpt-5.6") == {"summary": "auto"}
    assert service.reasoning_request_for_model("o4-mini") == {"summary": "auto"}
    assert service.reasoning_request_for_model("gpt-4o-mini") is None


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


def test_response_function_tools_include_configured_mcp_target() -> None:
    workspace_id = uuid4()
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/kubernetes",
        config_name="rancher-qa-omsllc",
        installed_version="1.0.0",
        status="enabled",
    )
    server = MCPServerVersion(
        id=uuid4(),
        name=installation.server_name,
        version=installation.installed_version,
        description="Kubernetes",
        server_json={},
        is_latest=True,
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        tool_name="create_namespace",
        title="Create namespace",
        description="Create a Kubernetes namespace.",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    runtime_tool = AgentRuntimeTool(
        wire_name="wardn_test",
        assignment_id=uuid4(),
        tool_schema=tool_schema,
        installation=installation,
        server=server,
    )

    description = provider_clients.response_function_tools({"wardn_test": runtime_tool})[0][
        "description"
    ]

    assert "Configured MCP target: rancher-qa-omsllc" in description
    assert f"MCP installation ID: {installation.id}" in description


def test_agent_dynamic_function_tools_expose_only_search_and_run() -> None:
    runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        description="[READ] List namespaces.",
    )

    function_tools = service.agent_dynamic_function_tools({"wardn_namespace": runtime_tool})

    assert [tool["name"] for tool in function_tools] == [
        service.AGENT_SEARCH_TOOLS_TOOL_NAME,
        service.AGENT_RUN_TOOL_TOOL_NAME,
    ]
    assert all(tool["name"] != "wardn_namespace" for tool in function_tools)
    assert service.agent_dynamic_function_tools({}) == []


def test_execute_agent_search_tools_returns_allowed_exact_tool_names() -> None:
    namespace_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        title="List namespaces",
        description="[READ] List Kubernetes namespaces.",
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Kubernetes target name.",
                }
            },
        },
        annotations={"readOnlyHint": True},
    )
    pod_tool = make_agent_runtime_tool(
        wire_name="wardn_pods",
        tool_name="pod_list",
        config_name="default",
        title="List pods",
        description="[READ] List Kubernetes pods.",
    )

    result = service.execute_agent_search_tools(
        {
            namespace_tool.wire_name: namespace_tool,
            pod_tool.wire_name: pod_tool,
        },
        service.AgentToolCall(
            name=service.AGENT_SEARCH_TOOLS_TOOL_NAME,
            call_id="call_1",
            arguments={"query": "list namespaces omsllc", "limit": 5},
        ),
    )
    payload = json.loads(result.output)

    assert result.status == "completed"
    assert payload["tools"][0]["toolName"] == "wardn_namespace"
    assert payload["tools"][0]["mcpToolName"] == "namespace_list"
    assert payload["tools"][0]["configuredTarget"] == "rancher-qa-omsllc"
    assert "route to this MCP installation" in payload["tools"][0]["configuredTargetHint"]
    assert payload["tools"][0]["readOnly"] is True
    assert payload["tools"][0]["params"][0]["name"] == "target"
    assert payload["tools"][0]["rank"] == 1
    assert payload["tools"][0]["score"] > 0
    assert payload["ranking"]["executable"][0]["toolName"] == "wardn_namespace"


def test_execute_agent_search_tools_does_not_treat_registry_prefix_as_github() -> None:
    github_tool = make_agent_runtime_tool(
        wire_name="wardn_github_prs",
        tool_name="search_pull_requests",
        server_name="io.github.github/github-mcp-server",
        title="Search pull requests",
        description="[READ] Search GitHub pull requests.",
    )
    k8s_tool = make_agent_runtime_tool(
        wire_name="wardn_k8s_logs",
        tool_name="pod_logs",
        server_name="io.github.AIops-tools/k8s-aiops",
        title="Read pod logs",
        description="[READ] Read Kubernetes pod logs.",
    )

    result = service.execute_agent_search_tools(
        {
            github_tool.wire_name: github_tool,
            k8s_tool.wire_name: k8s_tool,
        },
        service.AgentToolCall(
            name=service.AGENT_SEARCH_TOOLS_TOOL_NAME,
            call_id="call_1",
            arguments={"query": "github", "limit": 5},
        ),
    )
    payload = json.loads(result.output)

    assert payload["tools"][0]["mcpToolName"] == "search_pull_requests"
    assert payload["mcpMatches"][0]["mcpToolName"] == "search_pull_requests"
    assert payload["mcpMatchCount"] == 1
    assert "Executable MCP tools matched" in payload["executionGuidance"]
    assert all(tool["mcpToolName"] != "pod_logs" for tool in payload["tools"])


def test_execute_agent_search_tools_keeps_exact_registry_server_lookup() -> None:
    github_tool = make_agent_runtime_tool(
        wire_name="wardn_github_prs",
        tool_name="search_pull_requests",
        server_name="io.github.github/github-mcp-server",
        title="Search pull requests",
        description="[READ] Search GitHub pull requests.",
    )
    k8s_tool = make_agent_runtime_tool(
        wire_name="wardn_k8s_logs",
        tool_name="pod_logs",
        server_name="io.github.AIops-tools/k8s-aiops",
        title="Read pod logs",
        description="[READ] Read Kubernetes pod logs.",
    )

    result = service.execute_agent_search_tools(
        {
            github_tool.wire_name: github_tool,
            k8s_tool.wire_name: k8s_tool,
        },
        service.AgentToolCall(
            name=service.AGENT_SEARCH_TOOLS_TOOL_NAME,
            call_id="call_1",
            arguments={"query": "io.github.AIops-tools/k8s-aiops", "limit": 5},
        ),
    )
    payload = json.loads(result.output)

    assert payload["tools"][0]["mcpToolName"] == "pod_logs"
    assert payload["tools"][0]["serverName"] == "io.github.AIops-tools/k8s-aiops"


def test_execute_agent_search_tools_returns_enabled_skills_as_dynamic_results() -> None:
    result = service.execute_agent_search_tools(
        AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={}),
        service.AgentToolCall(
            name=service.AGENT_SEARCH_TOOLS_TOOL_NAME,
            call_id="call_1",
            arguments={"query": "wardn hub skills", "limit": 5},
        ),
        skill_tools=skills.agent_skill_function_tools([skills.WARDN_FIND_SKILLS_ID]),
    )
    payload = json.loads(result.output)

    assert result.status == "completed"
    assert [tool["toolName"] for tool in payload["tools"]] == [
        skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
        skills.WARDN_GET_SKILL_TOOL_NAME,
    ]
    assert payload["tools"][0]["toolType"] == "skill"
    assert payload["tools"][0]["skill"]["skillId"] == skills.WARDN_FIND_SKILLS_ID
    assert payload["tools"][0]["skill"]["installed"] is True
    assert payload["tools"][0]["skill"]["temporary"] is False
    assert payload["tools"][0]["skill"]["permissions"][-1]["key"] == "advisory_only"
    assert payload["totalReachable"] == 2
    assert payload["ranking"]["executable"][0]["toolType"] == "skill"


def test_execute_agent_search_tools_ranks_approved_skills_for_domain_queries() -> None:
    approved_skill = {
        "workspaceSkillId": str(uuid4()),
        "skillId": "owner/repo/github-pr-review",
        "name": "GitHub PR Review",
        "description": "Review pull requests with GitHub MCP tools and draft comments.",
        "url": "https://hub.wardnai.dev/skills/owner/repo/github-pr-review",
        "source": "owner/repo",
        "auditStatus": "pass",
        "auditScore": 94,
        "auditRank": "A",
    }

    result = service.execute_agent_search_tools(
        AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={}),
        service.AgentToolCall(
            name=service.AGENT_SEARCH_TOOLS_TOOL_NAME,
            call_id="call_1",
            arguments={"query": "github pr review", "limit": 5},
        ),
        skill_tools=skills.agent_skill_function_tools([], approved_skills=[approved_skill]),
    )
    payload = json.loads(result.output)

    assert result.status == "completed"
    assert payload["tools"][0]["toolName"] == skills.WARDN_SEARCH_SKILLS_TOOL_NAME
    assert payload["tools"][0]["approvedSkillMatches"][0]["skillId"] == (
        "owner/repo/github-pr-review"
    )
    assert "wardn_get_skill" in payload["tools"][0]["approvedSkillMatches"][0]["nextStep"]


def test_dynamic_tools_report_policy_denied_tools_without_fallback() -> None:
    allowed_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        title="List namespaces",
        description="[READ] List Kubernetes namespaces.",
    )
    denied_tool = make_agent_runtime_tool(
        wire_name="wardn_gsc_sites",
        tool_name="gsc_sites",
        server_name="io.github.acamolese/google-search-console-mcp",
        title="List Search Console sites",
        description="[READ] List Google Search Console sites.",
    )
    guardrail_filter = AgentRuntimeToolGuardrailFilter(
        allowed_tools={allowed_tool.wire_name: allowed_tool},
        denied_tools={
            denied_tool.wire_name: (
                denied_tool,
                GuardrailDecision(
                    mode="deny",
                    policy_name="workspace guardrail",
                    message="Tool call blocked by workspace policy.",
                ),
            )
        },
    )

    search = service.execute_agent_search_tools(
        guardrail_filter,
        service.AgentToolCall(
            name=service.AGENT_SEARCH_TOOLS_TOOL_NAME,
            call_id="call_1",
            arguments={"query": "search console sites", "limit": 5},
        ),
    )
    payload = json.loads(search.output)

    assert payload["tools"] == []
    assert payload["blockedTools"][0]["mcpToolName"] == "gsc_sites"
    assert payload["blockedTools"][0]["failureReason"] == "tool_assigned_blocked_policy"
    assert "Do not fall back" in payload["hint"]

    resolved = service.resolve_agent_run_tool_call(
        guardrail_filter,
        service.AgentToolCall(
            name=service.AGENT_RUN_TOOL_TOOL_NAME,
            call_id="call_2",
            arguments={"tool_name": "wardn_gsc_sites"},
        ),
    )

    assert not isinstance(resolved, tuple)
    assert resolved.status == "failed"
    assert resolved.failure_reason == "tool_assigned_blocked_policy"
    assert "blocked by policy" in (resolved.error or "")


def test_dynamic_run_tool_reports_installed_but_unassigned() -> None:
    installed_runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_gsc_sites",
        tool_name="gsc_sites",
        server_name="io.github.acamolese/google-search-console-mcp",
        title="List Search Console sites",
        description="[READ] List Google Search Console sites.",
    )
    guardrail_filter = AgentRuntimeToolGuardrailFilter(
        allowed_tools={},
        denied_tools={},
        installed_tools={
            str(installed_runtime_tool.tool_schema.id): service.AgentInstalledTool(
                tool_schema=installed_runtime_tool.tool_schema,
                installation=installed_runtime_tool.installation,
            )
        },
    )

    resolved = service.resolve_agent_run_tool_call(
        guardrail_filter,
        service.AgentToolCall(
            name=service.AGENT_RUN_TOOL_TOOL_NAME,
            call_id="call_1",
            arguments={"tool_name": "gsc_sites"},
        ),
    )

    assert not isinstance(resolved, tuple)
    assert resolved.status == "failed"
    assert resolved.failure_reason == "tool_installed_not_assigned"
    assert "not assigned to this agent" in (resolved.error or "")


def test_resolve_agent_run_tool_call_requires_exact_name_for_duplicates() -> None:
    default_tool = make_agent_runtime_tool(
        wire_name="wardn_default_namespace",
        tool_name="namespace_list",
        config_name="default",
    )
    rancher_tool = make_agent_runtime_tool(
        wire_name="wardn_rancher_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
    )
    tools = {
        default_tool.wire_name: default_tool,
        rancher_tool.wire_name: rancher_tool,
    }

    ambiguous = service.resolve_agent_run_tool_call(
        tools,
        service.AgentToolCall(
            name=service.AGENT_RUN_TOOL_TOOL_NAME,
            call_id="call_1",
            arguments={"tool_name": "namespace_list"},
        ),
    )

    assert not isinstance(ambiguous, tuple)
    assert ambiguous.status == "failed"
    assert "ambiguous" in (ambiguous.error or "")

    resolved = service.resolve_agent_run_tool_call(
        tools,
        service.AgentToolCall(
            name=service.AGENT_RUN_TOOL_TOOL_NAME,
            call_id="call_2",
            arguments={
                "tool_name": "wardn_rancher_namespace",
                "tool_args": {"target": "rancher-qa-omsllc", "namespace": "default"},
            },
        ),
    )

    assert isinstance(resolved, tuple)
    tool, target_call = resolved
    assert tool is rancher_tool
    assert target_call.name == "wardn_rancher_namespace"
    assert target_call.call_id == "call_2"
    assert target_call.arguments == {"namespace": "default"}


def test_resolve_agent_run_tool_call_disambiguates_duplicate_by_target_hint() -> None:
    default_tool = make_agent_runtime_tool(
        wire_name="wardn_default_namespace",
        tool_name="namespace_list",
        config_name="default",
    )
    rancher_tool = make_agent_runtime_tool(
        wire_name="wardn_rancher_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
    )

    resolved = service.resolve_agent_run_tool_call(
        {
            default_tool.wire_name: default_tool,
            rancher_tool.wire_name: rancher_tool,
        },
        service.AgentToolCall(
            name=service.AGENT_RUN_TOOL_TOOL_NAME,
            call_id="call_1",
            arguments={
                "tool_name": "namespace_list",
                "configured_target": "rancher-qa-omsllc",
                "tool_args": {},
            },
        ),
        request_meta={"userMessage": "list namespaces from rancher-qa omsllc"},
    )

    assert isinstance(resolved, tuple)
    tool, target_call = resolved
    assert tool is rancher_tool
    assert target_call.name == "wardn_rancher_namespace"


def test_resolve_agent_run_tool_call_keeps_required_target_argument() -> None:
    required_target_tool = make_agent_runtime_tool(
        wire_name="wardn_required_target",
        tool_name="required_target",
        config_name="rancher-qa-omsllc",
        input_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
            },
            "required": ["target"],
        },
    )

    resolved = service.resolve_agent_run_tool_call(
        {required_target_tool.wire_name: required_target_tool},
        service.AgentToolCall(
            name=service.AGENT_RUN_TOOL_TOOL_NAME,
            call_id="call_1",
            arguments={
                "tool_name": "wardn_required_target",
                "tool_args": {"target": "rancher-qa-omsllc"},
            },
        ),
    )

    assert isinstance(resolved, tuple)
    _tool, target_call = resolved
    assert target_call.arguments == {"target": "rancher-qa-omsllc"}


@pytest.mark.asyncio
async def test_execute_agent_dynamic_run_tool_stream_dispatches_enabled_skill(
    monkeypatch,
) -> None:
    skill_calls: list[tuple[str, dict]] = []

    async def execute_agent_skill_tool_call(tool_name, arguments, **kwargs):
        skill_calls.append((tool_name, arguments))
        return json.dumps({"count": 0})

    monkeypatch.setattr(
        chat_orchestrator,
        "execute_agent_skill_tool_call_with_context",
        execute_agent_skill_tool_call,
    )

    events = [
        event
        async for event in chat_orchestrator.execute_agent_dynamic_tool_call_stream(
            AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={}),
            service.AgentToolCall(
                name=service.AGENT_RUN_TOOL_TOOL_NAME,
                call_id="call_1",
                arguments={
                    "tool_name": skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
                    "tool_args": {"query": "kubernetes", "limit": 3},
                },
            ),
            skill_ids=[skills.WARDN_FIND_SKILLS_ID],
        )
    ]

    assert events[0].tool_name == "Tool selected"
    assert events[0].details["selection"]["toolType"] == "skill"
    assert events[-1].status == "completed"
    assert skill_calls == [
        (skills.WARDN_SEARCH_SKILLS_TOOL_NAME, {"query": "kubernetes", "limit": 3})
    ]


@pytest.mark.asyncio
async def test_execute_agent_dynamic_run_tool_stream_dispatches_resolved_target(
    monkeypatch,
) -> None:
    namespace_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        description="[READ] List Kubernetes namespaces.",
    )
    calls: list[dict] = []

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        calls.append(kwargs)
        return {"content": [{"type": "text", "text": "namespace data"}]}

    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    events = [
        event
        async for event in chat_orchestrator.execute_agent_dynamic_tool_call_stream(
            {namespace_tool.wire_name: namespace_tool},
            service.AgentToolCall(
                name=service.AGENT_RUN_TOOL_TOOL_NAME,
                call_id="call_1",
                arguments={
                    "tool_name": "wardn_namespace",
                    "tool_args": {"target": "rancher-qa-omsllc"},
                },
            ),
            session_factory=fake_session_factory(FakeSession()),
            request_meta={"userMessage": "list namespaces in rancher-qa omsllc"},
        )
    ]

    assert isinstance(events[0], service.AgentChatToolActivityEvent)
    assert events[0].tool_name == "Tool selected"
    assert events[0].details is not None
    selection = events[0].details["selection"]
    assert selection["selected"] == {
        "toolName": "namespace_list",
        "wireName": "wardn_namespace",
        "serverName": namespace_tool.server.name,
        "configuredTarget": "rancher-qa-omsllc",
        "installationId": str(namespace_tool.installation.id),
        "toolSchemaId": str(namespace_tool.tool_schema.id),
    }
    assert selection["targetDisambiguation"]["candidateCount"] == 1
    run_event = next(
        event
        for event in events
        if isinstance(event, service.AgentChatToolActivityEvent)
        and event.tool_name == "namespace_list"
        and event.arguments == {}
    )
    assert run_event.status == "running"
    assert isinstance(events[-1], service.AgentToolExecutionResult)
    assert events[-1].status == "completed"
    assert calls[0]["tool_name"] == "namespace_list"
    assert calls[0]["arguments"] == {}


@pytest.mark.asyncio
async def test_execute_agent_tool_call_with_progress_heartbeats_during_slow_runtime(
    monkeypatch,
) -> None:
    namespace_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        description="[READ] List Kubernetes namespaces.",
    )

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        await asyncio.sleep(0.03)
        return {"content": [{"type": "text", "text": "namespace data"}]}

    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )
    monkeypatch.setattr(tool_execution, "AGENT_TOOL_PROGRESS_HEARTBEAT_SECONDS", 0.005)

    events = [
        event
        async for event in tool_execution.execute_agent_tool_call_with_progress(
            {namespace_tool.wire_name: namespace_tool},
            service.AgentToolCall(
                name=namespace_tool.wire_name,
                call_id="call_1",
                arguments={},
            ),
            session_factory=fake_session_factory(FakeSession()),
            activity_id="tool-call-1",
            tool_name="namespace_list",
        )
    ]

    heartbeat = next(
        event
        for event in events
        if isinstance(event, service.AgentChatToolActivityEvent)
        and event.message == "Waiting for runtime result."
    )
    assert heartbeat.progress_token == "agent-tool:call_1"
    assert isinstance(events[-1], service.AgentToolExecutionResult)
    assert events[-1].status == "completed"


@pytest.mark.asyncio
async def test_stream_chatgpt_codex_exposes_dynamic_tools_instead_of_concrete_mcp(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="ChatGPT",
        provider=service.OPENAI_CHATGPT_PROVIDER,
        visibility="workspace",
        workspace_id=workspace_id,
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_metadata={"accountId": "account-1"},
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
        model_name="gpt-5.5",
        is_active=True,
    )
    runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    sent_bodies: list[dict] = []

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def send(self, message: str) -> None:
            sent_bodies.append(json.loads(message))

        def __aiter__(self):
            self.messages = iter(
                [
                    json.dumps(
                        {
                            "type": "response.completed",
                            "response": {
                                "id": "resp_1",
                                "usage": {
                                    "input_tokens": 1,
                                    "output_tokens": 0,
                                    "total_tokens": 1,
                                },
                            },
                        }
                    )
                ]
            )
            return self

        async def __anext__(self):
            try:
                return next(self.messages)
            except StopIteration:
                raise StopAsyncIteration from None

    def websocket_connect(*args, **kwargs):
        return FakeWebSocket()

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        return None

    monkeypatch.setattr(chat_orchestrator, "websocket_connect", websocket_connect)
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)

    events = [
        event
        async for event in service.stream_chatgpt_codex_response_text(
            agent,
            credential,
            session_factory=fake_session_factory(FakeSession()),
            headers={"Authorization": "Bearer token"},
            messages=[
                AgentChatMessage(role="user", parts=[{"type": "text", "text": "hello"}])
            ],
            tools={runtime_tool.wire_name: runtime_tool},
        )
    ]

    assert events == []
    assert [tool["name"] for tool in sent_bodies[0]["tools"]] == [
        service.AGENT_SEARCH_TOOLS_TOOL_NAME,
        service.AGENT_RUN_TOOL_TOOL_NAME,
    ]


@pytest.mark.asyncio
async def test_stream_chatgpt_codex_retries_round_websocket_drop_after_tool_result(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="ChatGPT",
        provider=service.OPENAI_CHATGPT_PROVIDER,
        visibility="workspace",
        workspace_id=workspace_id,
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_metadata={"accountId": "account-1"},
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
        model_name="gpt-5.5",
        is_active=True,
    )
    runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    sent_bodies: list[dict] = []
    usage_statuses: list[str] = []
    runtime_calls: list[dict] = []
    websocket_attempts = 0

    class FakeWebSocket:
        def __init__(self, messages: list[dict] | None = None, *, fail_before_output: bool = False):
            self.messages = [json.dumps(message) for message in (messages or [])]
            self.fail_before_output = fail_before_output

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def send(self, message: str) -> None:
            sent_bodies.append(json.loads(message))

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.fail_before_output:
                raise chat_orchestrator.WebSocketException(
                    "no close frame received or sent"
                )
            if not self.messages:
                raise StopAsyncIteration
            return self.messages.pop(0)

    def websocket_connect(*args, **kwargs):
        nonlocal websocket_attempts
        websocket_attempts += 1
        if websocket_attempts == 1:
            return FakeWebSocket(
                [
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "function_call",
                            "name": service.AGENT_RUN_TOOL_TOOL_NAME,
                            "call_id": "call_1",
                            "arguments": json.dumps(
                                {
                                    "tool_name": "namespace_list",
                                    "configured_target": "rancher-qa-omsllc",
                                    "tool_args": {},
                                }
                            ),
                        },
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_1",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    },
                ]
            )
        if websocket_attempts == 2:
            return FakeWebSocket(fail_before_output=True)
        return FakeWebSocket(
            [
                {"type": "response.output_text.delta", "delta": "done"},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_2",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                },
            ]
        )

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        usage_statuses.append(kwargs["status"])

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        runtime_calls.append(kwargs)
        return {"content": [{"type": "text", "text": "namespace data"}]}

    monkeypatch.setattr(chat_orchestrator, "websocket_connect", websocket_connect)
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)
    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    events = [
        event
        async for event in service.stream_chatgpt_codex_response_text(
            agent,
            credential,
            session_factory=fake_session_factory(FakeSession()),
            headers={"Authorization": "Bearer token"},
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=[{"type": "text", "text": "list namespaces in rancher-qa"}],
                )
            ],
            tools={runtime_tool.wire_name: runtime_tool},
        )
    ]

    text_events = [event.text for event in events if isinstance(event, service.AgentChatTextEvent)]
    assert text_events == ["done"]
    assert len(sent_bodies) == 3
    assert "store" not in sent_bodies[0]
    assert sent_bodies[1]["previous_response_id"] == "resp_1"
    assert "store" not in sent_bodies[1]
    assert sent_bodies[1]["input"] == sent_bodies[2]["input"]
    assert sent_bodies[2]["previous_response_id"] == "resp_1"
    assert "store" not in sent_bodies[2]
    assert sent_bodies[1]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "namespace data",
        }
    ]
    assert len(runtime_calls) == 1
    assert runtime_calls[0]["tool_name"] == "namespace_list"
    assert usage_statuses == ["succeeded", "succeeded"]


@pytest.mark.asyncio
async def test_stream_chatgpt_codex_times_out_when_provider_stalls(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="ChatGPT",
        provider=service.OPENAI_CHATGPT_PROVIDER,
        visibility="workspace",
        workspace_id=workspace_id,
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_metadata={"accountId": "account-1"},
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
        model_name="gpt-5.5",
        is_active=True,
    )
    sent_bodies: list[dict] = []
    usage_statuses: list[str] = []

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def send(self, message: str) -> None:
            sent_bodies.append(json.loads(message))

        async def __anext__(self):
            await asyncio.sleep(0.05)
            return json.dumps({"type": "response.created"})

    def websocket_connect(*args, **kwargs):
        return FakeWebSocket()

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        usage_statuses.append(kwargs["status"])

    monkeypatch.setattr(chat_orchestrator, "websocket_connect", websocket_connect)
    monkeypatch.setattr(
        chat_orchestrator,
        "agent_chat_websocket_response_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)

    with pytest.raises(service.AgentChatProviderError, match="did not send a response"):
        [
            event
            async for event in service.stream_chatgpt_codex_response_text(
                agent,
                credential,
                session_factory=fake_session_factory(FakeSession()),
                headers={"Authorization": "Bearer token"},
                messages=[
                    AgentChatMessage(role="user", parts=[{"type": "text", "text": "hello"}])
                ],
                tools={},
            )
        ]

    assert len(sent_bodies) == 1
    assert usage_statuses == ["failed"]


@pytest.mark.asyncio
async def test_stream_openai_responses_uses_dynamic_tools_and_runs_resolved_target(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
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
        model_name="gpt-5.1",
        is_active=True,
    )
    runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    sent_bodies: list[dict] = []
    runtime_calls: list[dict] = []

    async def stream_response_events(*args, **kwargs):
        sent_bodies.append(kwargs["body"])
        if len(sent_bodies) == 1:
            yield {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "name": service.AGENT_RUN_TOOL_TOOL_NAME,
                    "call_id": "call_1",
                    "arguments": json.dumps(
                        {
                            "tool_name": "namespace_list",
                            "configured_target": "rancher-qa-omsllc",
                            "tool_args": {},
                        }
                    ),
                },
            }
            yield {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            }
            return
        yield {"type": "response.output_text.delta", "delta": "done"}
        yield {
            "type": "response.completed",
            "response": {
                "id": "resp_2",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        return None

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        runtime_calls.append(kwargs)
        return {"content": [{"type": "text", "text": "namespace data"}]}

    monkeypatch.setattr(chat_orchestrator, "stream_response_events", stream_response_events)
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)
    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    events = [
        event
        async for event in chat_orchestrator.stream_openai_responses_response_text(
            agent,
            credential,
            session_factory=fake_session_factory(FakeSession()),
            headers={"Authorization": "Bearer sk-test"},
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=[{"type": "text", "text": "list namespaces in rancher-qa"}],
                )
            ],
            tools={runtime_tool.wire_name: runtime_tool},
        )
    ]

    assert [tool["name"] for tool in sent_bodies[0]["tools"]] == [
        service.AGENT_SEARCH_TOOLS_TOOL_NAME,
        service.AGENT_RUN_TOOL_TOOL_NAME,
    ]
    assert all(tool["name"] != "wardn_namespace" for tool in sent_bodies[0]["tools"])
    assert sent_bodies[1]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "namespace data",
        }
    ]
    assert runtime_calls[0]["tool_name"] == "namespace_list"
    assert [event.text for event in events if isinstance(event, service.AgentChatTextEvent)] == [
        "done"
    ]


@pytest.mark.asyncio
async def test_stream_openai_responses_injects_skill_guidance_for_scheduled_runs(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
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
        model_name="gpt-5.1",
        skill_ids=[],
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        triggered_by_id=uuid4(),
        trigger_type="scheduled",
        status="running",
        started_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    workspace_skill = WorkspaceApprovedSkill(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        approved_by_id=uuid4(),
        skill_id="owner/repo/github-pr-review",
        name="GitHub PR Review",
        description="Review pull requests with GitHub MCP tools and draft comments.",
        url="https://hub.wardnai.dev/skills/owner/repo/github-pr-review",
        source="owner/repo",
        source_url="https://github.com/owner/repo",
        source_owner="owner",
        source_name="repo",
        audit_status="pass",
        audit_score=94,
        audit_rank="A",
        audit_summary="Looks safe.",
        content_hash="abc123",
        status="active",
        metadata_json={},
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        updated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    sent_bodies: list[dict] = []

    async def list_agent_approved_skills(*args, **kwargs):
        assert kwargs["agent_id"] == agent.id
        return [workspace_skill]

    async def stream_response_events(*args, **kwargs):
        sent_bodies.append(kwargs["body"])
        yield {
            "type": "response.completed",
            "response": {
                "id": "resp_1",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        }

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        return None

    monkeypatch.setattr(
        chat_orchestrator.repository,
        "list_agent_approved_skills",
        list_agent_approved_skills,
    )
    monkeypatch.setattr(chat_orchestrator, "stream_response_events", stream_response_events)
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)

    events = [
        event
        async for event in chat_orchestrator.stream_openai_responses_response_text(
            agent,
            credential,
            session_factory=fake_session_factory(FakeSession()),
            headers={"Authorization": "Bearer sk-test"},
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=[{"type": "text", "text": "Review GitHub PRs assigned to me"}],
                )
            ],
            tools=AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={}),
            agent_run=agent_run,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    ]

    assert events == []
    assert [tool["name"] for tool in sent_bodies[0]["tools"]] == [
        service.AGENT_SEARCH_TOOLS_TOOL_NAME,
        service.AGENT_RUN_TOOL_TOOL_NAME,
    ]
    assert "GitHub PR Review" in sent_bodies[0]["instructions"]
    assert "scheduled run" in sent_bodies[0]["instructions"]
    assert "search_tools" in sent_bodies[0]["instructions"]


@pytest.mark.asyncio
async def test_stream_openai_responses_uses_configured_tool_round_limit(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
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
        model_name="gpt-5.1",
        is_active=True,
    )
    runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        config_name="rancher-qa-omsllc",
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    sent_bodies: list[dict] = []

    async def stream_response_events(*args, **kwargs):
        sent_bodies.append(kwargs["body"])
        yield {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": service.AGENT_RUN_TOOL_TOOL_NAME,
                "call_id": f"call_{len(sent_bodies)}",
                "arguments": json.dumps(
                    {
                        "tool_name": "namespace_list",
                        "configured_target": "rancher-qa-omsllc",
                        "tool_args": {},
                    }
                ),
            },
        }
        yield {
            "type": "response.completed",
            "response": {
                "id": f"resp_{len(sent_bodies)}",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }

    async def agent_chat_max_tool_rounds(*args, **kwargs):
        return 1

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        return None

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        return {"content": [{"type": "text", "text": "namespace data"}]}

    monkeypatch.setattr(chat_orchestrator, "stream_response_events", stream_response_events)
    monkeypatch.setattr(
        chat_orchestrator,
        "agent_chat_max_tool_rounds",
        agent_chat_max_tool_rounds,
    )
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)
    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    events = [
        event
        async for event in chat_orchestrator.stream_openai_responses_response_text(
            agent,
            credential,
            session_factory=fake_session_factory(FakeSession()),
            user=User(id=uuid4(), email="owner@example.com"),
            organization_id=organization_id,
            workspace_id=workspace_id,
            headers={"Authorization": "Bearer sk-test"},
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=[{"type": "text", "text": "list namespaces in rancher-qa"}],
                )
            ],
            tools={runtime_tool.wire_name: runtime_tool},
        )
    ]

    text_events = [event.text for event in events if isinstance(event, service.AgentChatTextEvent)]
    assert text_events[-1] == (
        "\n\nStopped after reaching the configured tool call limit (1)."
    )
    assert len(sent_bodies) == 1


@pytest.mark.asyncio
async def test_stream_chatgpt_codex_refuses_unadvertised_direct_mcp_call(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="ChatGPT",
        provider=service.OPENAI_CHATGPT_PROVIDER,
        visibility="workspace",
        workspace_id=workspace_id,
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_metadata={"accountId": "account-1"},
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
        model_name="gpt-5.5",
        is_active=True,
    )
    runtime_tool = make_agent_runtime_tool(
        wire_name="wardn_namespace",
        tool_name="namespace_list",
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    sent_bodies: list[dict] = []
    runtime_calls: list[dict] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def send(self, message: str) -> None:
            sent_bodies.append(json.loads(message))
            if len(sent_bodies) == 1:
                self.messages = [
                    json.dumps(
                        {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "function_call",
                                "name": "wardn_namespace",
                                "call_id": "call_1",
                                "arguments": "{}",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "response.completed",
                            "response": {
                                "id": "resp_1",
                                "usage": {"input_tokens": 1, "output_tokens": 1},
                            },
                        }
                    ),
                ]
            else:
                self.messages = [
                    json.dumps(
                        {
                            "type": "response.completed",
                            "response": {
                                "id": "resp_2",
                                "usage": {"input_tokens": 1, "output_tokens": 0},
                            },
                        }
                    )
                ]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.messages:
                raise StopAsyncIteration
            return self.messages.pop(0)

    def websocket_connect(*args, **kwargs):
        return FakeWebSocket()

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        return None

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        runtime_calls.append(kwargs)
        return {"content": [{"type": "text", "text": "should not run"}]}

    monkeypatch.setattr(chat_orchestrator, "websocket_connect", websocket_connect)
    monkeypatch.setattr(
        chat_orchestrator,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(chat_orchestrator, "record_agent_llm_usage", record_agent_llm_usage)
    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    events = [
        event
        async for event in service.stream_chatgpt_codex_response_text(
            agent,
            credential,
            session_factory=fake_session_factory(FakeSession()),
            headers={"Authorization": "Bearer token"},
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=[{"type": "text", "text": "list namespaces"}],
                )
            ],
            tools={runtime_tool.wire_name: runtime_tool},
        )
    ]

    completed = [
        event
        for event in events
        if isinstance(event, service.AgentChatToolActivityEvent)
        and event.status == "failed"
    ]
    assert completed[0].tool_name == "namespace_list"
    assert completed[0].error is not None
    assert "direct tool calls are not available" in completed[0].error
    assert runtime_calls == []


@pytest.mark.asyncio
async def test_execute_agent_tool_blocks_ambiguous_duplicate_mutating_target(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    server_name = "io.github.example/kubernetes"
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=server_name,
        version="1.0.0",
        description="Kubernetes",
        server_json={},
        is_latest=True,
        status="active",
    )

    def runtime_tool(wire_name: str, config_name: str) -> AgentRuntimeTool:
        installation = MCPServerInstallation(
            id=uuid4(),
            workspace_id=workspace_id,
            server_name=server_name,
            config_name=config_name,
            installed_version="1.0.0",
            status="enabled",
        )
        tool_schema = MCPServerToolSchema(
            id=uuid4(),
            workspace_id=workspace_id,
            installation_id=installation.id,
            server_name=server_name,
            server_version="1.0.0",
            tool_name="create_namespace",
            title="Create namespace",
            description="Create a Kubernetes namespace.",
            input_schema={"type": "object"},
            annotations={},
            is_active=True,
        )
        return AgentRuntimeTool(
            wire_name=wire_name,
            assignment_id=uuid4(),
            tool_schema=tool_schema,
            installation=installation,
            server=server,
        )

    tools = {
        "default": runtime_tool("default", "default"),
        "rancher": runtime_tool("rancher", "rancher-qa-omsllc"),
    }

    calls = []

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        calls.append(kwargs["tool_name"])
        return {"content": [{"type": "text", "text": "created"}]}

    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    result = await tool_execution._execute_agent_tool_call(
        FakeSession(),
        tools,
        service.AgentToolCall(
            name="default",
            call_id="call_1",
            arguments={"name": "test-ns"},
        ),
        request_meta={"userMessage": "create a namespace in rancher-qa"},
    )

    assert result.status == "blocked"
    assert result.error is not None
    assert result.output.startswith(service.AGENT_TOOL_TARGET_SAFETY_PREFIX)
    assert "default" in result.output
    assert "rancher-qa-omsllc" in result.output
    assert calls == []

    result = await tool_execution._execute_agent_tool_call(
        FakeSession(),
        tools,
        service.AgentToolCall(
            name="rancher",
            call_id="call_2",
            arguments={"name": "test-ns"},
        ),
        request_meta={"userMessage": "create a namespace in rancher-qa"},
    )

    assert result.status == "completed"
    assert result.output == "created"
    assert calls == ["create_namespace"]


@pytest.mark.asyncio
async def test_execute_agent_tool_allows_duplicate_read_only_targets(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    server_name = "io.github.example/kubernetes"
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=server_name,
        version="1.0.0",
        description="Kubernetes",
        server_json={},
        is_latest=True,
        status="active",
    )
    calls = []

    def runtime_tool(wire_name: str, config_name: str) -> AgentRuntimeTool:
        installation = MCPServerInstallation(
            id=uuid4(),
            workspace_id=workspace_id,
            server_name=server_name,
            config_name=config_name,
            installed_version="1.0.0",
            status="enabled",
        )
        tool_schema = MCPServerToolSchema(
            id=uuid4(),
            workspace_id=workspace_id,
            installation_id=installation.id,
            server_name=server_name,
            server_version="1.0.0",
            tool_name="cluster_info",
            title="Cluster info",
            description="Read Kubernetes cluster information.",
            input_schema={"type": "object"},
            annotations={"readOnlyHint": True},
            is_active=True,
        )
        return AgentRuntimeTool(
            wire_name=wire_name,
            assignment_id=uuid4(),
            tool_schema=tool_schema,
            installation=installation,
            server=server,
        )

    tools = {
        "default": runtime_tool("default", "default"),
        "rancher": runtime_tool("rancher", "rancher-qa-omsllc"),
    }

    async def call_tool_with_isolated_tracking(*args, **kwargs):
        calls.append(kwargs["tool_name"])
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_isolated_tracking,
    )

    result = await tool_execution._execute_agent_tool_call(
        FakeSession(),
        tools,
        service.AgentToolCall(name="default", call_id="call_1", arguments={}),
    )

    assert result.status == "completed"
    assert result.output == "ok"
    assert calls == ["cluster_info"]


def test_agent_skill_function_tools_are_available_when_find_skills_is_installed() -> None:
    assert skills.agent_skill_function_tools([]) == []

    function_tools = skills.agent_skill_function_tools([skills.WARDN_FIND_SKILLS_ID])

    assert [tool["name"] for tool in function_tools] == [
        skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
        skills.WARDN_GET_SKILL_TOOL_NAME,
    ]


def test_agent_skill_function_tools_are_available_for_approved_workspace_library() -> None:
    approved_skills = [{"skillId": "owner/repo/kubernetes-ops", "name": "Kubernetes ops"}]

    function_tools = skills.agent_skill_function_tools([], approved_skills=approved_skills)

    assert [tool["name"] for tool in function_tools] == [
        skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
        skills.WARDN_GET_SKILL_TOOL_NAME,
    ]
    assert skills.is_agent_skill_tool_enabled(
        [],
        skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
        approved_skills=approved_skills,
    )


def test_agent_runtime_instructions_adds_scheduled_skill_guidance() -> None:
    agent = Agent(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        name="Assistant",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-5.1",
        is_active=True,
    )
    run = AgentRun(
        id=uuid4(),
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        triggered_by_id=uuid4(),
        trigger_type="scheduled",
        status="running",
        started_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    approved_skill = {
        "workspaceSkillId": str(uuid4()),
        "skillId": "owner/repo/github-pr-review",
        "name": "GitHub PR Review",
        "description": "Review pull requests with GitHub MCP tools.",
    }

    instructions = chat_orchestrator.agent_runtime_instructions(
        agent,
        skill_tools=skills.agent_skill_function_tools([], approved_skills=[approved_skill]),
        approved_skill_context=[approved_skill],
        agent_run=run,
    )

    assert instructions.startswith("Help.")
    assert "Wardn runtime skills" in instructions
    assert "scheduled run" in instructions
    assert "GitHub PR Review (owner/repo/github-pr-review)" in instructions
    assert "search_tools" in instructions


@pytest.mark.asyncio
async def test_execute_agent_skill_tool_searches_wardn_hub(monkeypatch) -> None:
    class FakeHubClient:
        requests: list[tuple[str, dict | None]] = []

        def __init__(self, *args, **kwargs) -> None:
            self.options = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url, params=None):
            self.requests.append((url, params))
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": skills.WARDN_FIND_SKILLS_ID,
                            "name": "find-skills",
                            "description": "Discover skills.",
                            "url": skills.WARDN_FIND_SKILLS_URL,
                            "isOfficial": False,
                            "installs": 7,
                            "auditStatus": "pass",
                            "auditScore": 100,
                            "auditRank": "S",
                        }
                    ]
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(skills.httpx, "AsyncClient", FakeHubClient)

    output = await skills.execute_agent_skill_tool_call(
        skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
        {"query": "kubernetes", "limit": 99},
    )
    payload = json.loads(output)

    assert FakeHubClient.requests == [
        (
            "https://hub.wardnai.dev/api/v1/skills/search",
            {"q": "kubernetes", "limit": skills.WARDN_SKILL_SEARCH_MAX_RESULTS},
        )
    ]
    assert payload["results"][0]["id"] == skills.WARDN_FIND_SKILLS_ID
    assert payload["results"][0]["auditStatus"] == "pass"


@pytest.mark.asyncio
async def test_execute_agent_skill_tool_fetches_audited_bundle(monkeypatch) -> None:
    class FakeHubClient:
        requests: list[tuple[str, dict | None]] = []

        def __init__(self, *args, **kwargs) -> None:
            self.options = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url, params=None):
            self.requests.append((url, params))
            if url.endswith(f"/audit/{skills.WARDN_FIND_SKILLS_ID}"):
                return httpx.Response(
                    200,
                    json={
                        "id": skills.WARDN_FIND_SKILLS_ID,
                        "contentHash": "a" * 64,
                        "audit": {
                            "status": "pass",
                            "riskLevel": "low",
                            "score": 100,
                            "rank": "S",
                            "summary": "No known threat patterns.",
                            "scoreDeductions": [],
                            "findings": [],
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                json={
                    "id": skills.WARDN_FIND_SKILLS_ID,
                    "source": "abhi1693/wardn-hub",
                    "sourceUrl": "https://github.com/abhi1693/wardn-hub",
                    "hash": "a" * 64,
                    "sourceEntrypoint": "SKILL.md",
                    "bundleFormatVersion": 2,
                    "resolutionStatus": "complete",
                    "resolutionIssues": [],
                    "files": [
                        {
                            "path": "SKILL.md",
                            "contents": "# Find Skills\n\nUse public registry search.",
                        },
                        {"path": "LICENSE", "contents": "Apache-2.0"},
                    ],
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(skills.httpx, "AsyncClient", FakeHubClient)

    output = await skills.execute_agent_skill_tool_call(
        skills.WARDN_GET_SKILL_TOOL_NAME,
        {"skillId": skills.WARDN_FIND_SKILLS_ID},
    )
    payload = json.loads(output)

    assert FakeHubClient.requests == [
        (f"https://hub.wardnai.dev/api/v1/skills/audit/{skills.WARDN_FIND_SKILLS_ID}", None),
        (
            f"https://hub.wardnai.dev/api/v1/skills/{skills.WARDN_FIND_SKILLS_ID}",
            {"include_bundle": "true", "content_hash": "a" * 64},
        ),
    ]
    assert payload["audit"]["status"] == "pass"
    assert payload["files"][0]["path"] == "SKILL.md"
    assert payload["skillMarkdown"].startswith("# Find Skills")


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

    async def count_active_tool_schemas(*args, **kwargs):
        assert kwargs["installation_id"] == installation.id
        return 0

    monkeypatch.setattr(
        service.repository,
        "list_agent_wildcard_server_version_rows",
        list_agent_wildcard_server_version_rows,
    )
    monkeypatch.setattr(
        service.mcp_tool_repository,
        "count_active_tool_schemas",
        count_active_tool_schemas,
    )
    monkeypatch.setattr(
        service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )

    session = FakeSession()
    failures = await service.refresh_wildcard_agent_server_tools(session, agent_id)

    assert refreshed == [(installation, server)]
    assert failures == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_refresh_wildcard_agent_server_tools_skips_cached_server_tools(monkeypatch) -> None:
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
    cached_checks = []
    refreshed = []

    async def list_agent_wildcard_server_version_rows(*args, **kwargs):
        assert kwargs["agent_id"] == agent_id
        return [(assignment, installation, server)]

    async def count_active_tool_schemas(*args, **kwargs):
        cached_checks.append(kwargs)
        return 8

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        refreshed.append((kwargs["installation"], kwargs["server"]))

    monkeypatch.setattr(
        service.repository,
        "list_agent_wildcard_server_version_rows",
        list_agent_wildcard_server_version_rows,
    )
    monkeypatch.setattr(
        service.mcp_tool_repository,
        "count_active_tool_schemas",
        count_active_tool_schemas,
    )
    monkeypatch.setattr(
        service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )

    failures = await service.refresh_wildcard_agent_server_tools(FakeSession(), agent_id)

    assert failures == []
    assert refreshed == []
    assert cached_checks == [
        {
            "installation_id": installation.id,
            "server_name": installation.server_name,
            "server_version": installation.installed_version,
        }
    ]


@pytest.mark.asyncio
async def test_refresh_wildcard_agent_server_tools_returns_failed_servers(
    monkeypatch,
    caplog,
) -> None:
    agent_id = uuid4()
    assignment = AgentMCPServerAssignment(
        id=uuid4(),
        agent_id=agent_id,
        installation_id=uuid4(),
    )
    installation = MCPServerInstallation(
        id=assignment.installation_id,
        workspace_id=uuid4(),
        server_name="io.github.example/failing-server",
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

    async def list_agent_wildcard_server_version_rows(*args, **kwargs):
        assert kwargs["agent_id"] == agent_id
        return [(assignment, installation, server)]

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        raise service.MCPGatewayUpstreamError("upstream initialize returned no result")

    async def count_active_tool_schemas(*args, **kwargs):
        return 0

    monkeypatch.setattr(
        service.repository,
        "list_agent_wildcard_server_version_rows",
        list_agent_wildcard_server_version_rows,
    )
    monkeypatch.setattr(
        service.mcp_tool_repository,
        "count_active_tool_schemas",
        count_active_tool_schemas,
    )
    monkeypatch.setattr(
        service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )

    session = FakeSession()
    with caplog.at_level(logging.WARNING, logger=service.logger.name):
        failures = await service.refresh_wildcard_agent_server_tools(session, agent_id)

    assert failures == [
        service.AgentToolRefreshFailure(
            installation_id=installation.id,
            server_name=installation.server_name,
            server_version=installation.installed_version,
            config_name=installation.config_name,
            error_type="MCPGatewayUpstreamError",
            error="upstream initialize returned no result",
        )
    ]
    assert "cached tools remain eligible" in caplog.text
    assert session.commits == 0


@pytest.mark.asyncio
async def test_stream_agent_chat_keeps_cached_tools_after_refresh_failure(monkeypatch) -> None:
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
    assignment = AgentMCPServerAssignment(
        id=uuid4(),
        agent_id=agent.id,
        installation_id=uuid4(),
    )
    installation = MCPServerInstallation(
        id=assignment.installation_id,
        workspace_id=workspace_id,
        server_name="io.github.markswendsen-code/gmail",
        config_name="desk.abhimanyu",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version=installation.installed_version,
        description="Gmail",
        server_json={},
        packages=[],
        remotes=[],
        icons=[],
        is_latest=True,
        status="active",
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        tool_name="send_email",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    failure = service.AgentToolRefreshFailure(
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        config_name=installation.config_name,
        error_type="MCPGatewayUpstreamError",
        error="upstream initialize returned no result",
    )
    steps: list[dict] = []
    seen_filter_tools: list[dict] = []
    seen_provider_tools: list[dict] = []

    async def get_agent_model_for_run(*args, **kwargs):
        return agent, credential

    async def create_agent_run(*args, **kwargs):
        return agent_run

    async def append_agent_run_step(*args, **kwargs):
        steps.append(kwargs)

    async def finish_agent_run(*args, **kwargs):
        return None

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def refresh_wildcard_agent_server_tools(*args, **kwargs):
        return [failure]

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        return [(assignment, tool_schema, installation, server)]

    async def filter_agent_runtime_tools_for_guardrails(*args, **kwargs):
        seen_filter_tools.append(args[1])
        return AgentRuntimeToolGuardrailFilter(allowed_tools=args[1], denied_tools={})

    async def run_agent_chat(*args, **kwargs):
        seen_provider_tools.append(args[3])
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
                AgentChatMessage(role="user", parts=[{"type": "text", "text": "send mail"}])
            ]
        ),
        workspace_id=workspace_id,
        session_factory=fake_session_factory(FakeSession()),
    )
    chunks = ui_stream_chunks([chunk async for chunk in stream])

    wire_name = service.agent_runtime_tools(
        [(assignment, tool_schema, installation, server)]
    ).popitem()[0]
    assert wire_name in seen_filter_tools[0]
    assert wire_name in seen_provider_tools[0].allowed_tools
    assert steps[1]["step_type"] == "tool_discovery"
    assert steps[1]["status"] == "failed"
    assert chunks[-1] == {"type": "finish", "finishReason": "stop"}


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
    assert agent.skill_ids == [skills.WARDN_FIND_SKILLS_ID]
    assert response.agent.skill_ids == [skills.WARDN_FIND_SKILLS_ID]
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
    monkeypatch.setattr(
        provider_clients,
        "credential_supports_model",
        credential_supports_model,
    )
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
    assert response.agent.skill_ids == []
    assert response.agent.provider_credential_id == credential.id
    assert response.agent.model_name == "gpt-4o-mini"
    assert isinstance(session.added[0], WorkspaceConversation)
    assert response.conversation.agent_id == agent.id
    assert response.messages == []
    assert sync_calls == [agent.id]


@pytest.mark.asyncio
async def test_update_workspace_assistant_model_updates_existing_agent(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    credential = LLMProviderCredential(
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
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        provider_credential_id=uuid4(),
        name=service.QUICK_START_AGENT_NAME,
        description="",
        instructions="",
        scope="workspace",
        model_name="gpt-4o-mini",
        skill_ids=[],
        is_active=False,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/server",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    assigned_servers = []

    async def require_agent_scope_permission(*args, **kwargs):
        assert kwargs["scope"] == "workspace"
        assert kwargs["workspace_id"] == workspace_id
        return workspace_id

    async def validate_provider_credential(*args, **kwargs):
        assert kwargs["agent_workspace_id"] == workspace_id
        assert kwargs["provider_credential_id"] == credential.id
        return credential

    async def validate_agent_model(*args, **kwargs):
        assert args[1] is credential
        assert args[2] == "gpt-5.1"
        return "gpt-5.1"

    async def get_agent_by_name(*args, **kwargs):
        assert kwargs["name"] == service.QUICK_START_AGENT_NAME
        return agent

    async def require_agent_create_limit(*args, **kwargs):
        raise AssertionError("existing workspace assistant should not consume agent quota")

    async def list_installations(*args, **kwargs):
        return [installation]

    async def replace_agent_tools(*args, **kwargs):
        assigned_servers.extend(kwargs["server_assignments"])

    async def count_agent_servers(*args, **kwargs):
        return 1

    async def count_agent_tools(*args, **kwargs):
        return 4

    monkeypatch.setattr(
        service,
        "require_agent_scope_permission",
        require_agent_scope_permission,
    )
    monkeypatch.setattr(service, "validate_provider_credential", validate_provider_credential)
    monkeypatch.setattr(service, "validate_agent_model", validate_agent_model)
    monkeypatch.setattr(service.repository, "get_agent_by_name", get_agent_by_name)
    monkeypatch.setattr(service, "require_agent_create_limit", require_agent_create_limit)
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "count_agent_servers", count_agent_servers)
    monkeypatch.setattr(service.repository, "count_agent_tools", count_agent_tools)

    response = await service.update_workspace_assistant_model(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
        WorkspaceAgentModelUpdate(
            providerCredentialId=credential.id,
            modelName="gpt-5.1",
        ),
    )

    assert agent.provider_credential_id == credential.id
    assert agent.model_name == "gpt-5.1"
    assert agent.scope == "workspace"
    assert agent.workspace_id == workspace_id
    assert agent.description == service.QUICK_START_AGENT_DESCRIPTION
    assert agent.instructions == service.QUICK_START_AGENT_INSTRUCTIONS
    assert agent.skill_ids == []
    assert agent.is_active is True
    assert assigned_servers == [(installation, True, [])]
    assert response.provider_credential_id == credential.id
    assert response.model_name == "gpt-5.1"
    assert response.server_count == 1
    assert response.tool_count == 4


@pytest.mark.asyncio
async def test_update_workspace_assistant_model_creates_missing_agent(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    credential = LLMProviderCredential(
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
    create_limit_calls = 0

    async def require_agent_scope_permission(*args, **kwargs):
        return workspace_id

    async def validate_provider_credential(*args, **kwargs):
        return credential

    async def validate_agent_model(*args, **kwargs):
        return "gpt-5.1"

    async def get_agent_by_name(*args, **kwargs):
        return None

    async def require_agent_create_limit(*args, **kwargs):
        nonlocal create_limit_calls
        create_limit_calls += 1

    async def list_installations(*args, **kwargs):
        return []

    async def replace_agent_tools(*args, **kwargs):
        assert kwargs["server_assignments"] == []

    async def count_agent_servers(*args, **kwargs):
        return 0

    async def count_agent_tools(*args, **kwargs):
        return 0

    monkeypatch.setattr(
        service,
        "require_agent_scope_permission",
        require_agent_scope_permission,
    )
    monkeypatch.setattr(service, "validate_provider_credential", validate_provider_credential)
    monkeypatch.setattr(service, "validate_agent_model", validate_agent_model)
    monkeypatch.setattr(service.repository, "get_agent_by_name", get_agent_by_name)
    monkeypatch.setattr(service, "require_agent_create_limit", require_agent_create_limit)
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "count_agent_servers", count_agent_servers)
    monkeypatch.setattr(service.repository, "count_agent_tools", count_agent_tools)

    session = FakeSession()
    response = await service.update_workspace_assistant_model(
        session,
        user,
        organization_id,
        workspace_id,
        WorkspaceAgentModelUpdate(
            providerCredentialId=credential.id,
            modelName="gpt-5.1",
        ),
    )

    agent = session.added[0]
    assert isinstance(agent, Agent)
    assert agent.name == service.QUICK_START_AGENT_NAME
    assert agent.description == service.QUICK_START_AGENT_DESCRIPTION
    assert agent.instructions == service.QUICK_START_AGENT_INSTRUCTIONS
    assert agent.provider_credential_id == credential.id
    assert agent.model_name == "gpt-5.1"
    assert agent.skill_ids == [skills.WARDN_FIND_SKILLS_ID]
    assert agent.is_active is True
    assert response.id == agent.id
    assert create_limit_calls == 1


@pytest.mark.asyncio
async def test_list_workspace_skills_returns_find_skills_status_and_recommendations(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-4o-mini",
        skill_ids=[skills.WARDN_FIND_SKILLS_ID],
        is_active=True,
    )
    now = datetime.now(UTC)
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/rancher-kubernetes",
        config_name="rancher-qa",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={"provider": "kubernetes"},
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        trigger_type="chat",
        status="succeeded",
        started_at=now,
        finished_at=now,
        error="",
    )
    skill_step = AgentRunStep(
        id=uuid4(),
        agent_run_id=agent_run.id,
        sequence=1,
        step_type="tool_result",
        status="completed",
        title="Wardn Hub skill search",
        payload={
            "toolName": "Wardn Hub skill search",
            "status": "completed",
            "arguments": {"query": "kubernetes ops", "limit": 8},
            "result": json.dumps(
                {
                    "query": "kubernetes ops",
                    "count": 1,
                    "results": [
                        {
                            "id": "owner/repo/kubernetes-ops",
                            "auditStatus": "pass",
                        }
                    ],
                }
            ),
            "details": {
                "skill": {
                    "skillId": skills.WARDN_FIND_SKILLS_ID,
                    "skillName": "find-skills",
                    "source": "abhi1693/wardn-hub",
                    "toolName": skills.WARDN_SEARCH_SKILLS_TOOL_NAME,
                }
            },
        },
        created_at=now,
        updated_at=now,
    )

    async def require_workspace_member(*args, **kwargs):
        return None, None, None

    async def list_agents(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return [(agent, 0, 0)], ""

    async def list_installations(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return [installation]

    async def list_recent_workspace_agent_run_steps(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return [(skill_step, agent_run, agent)]

    async def fetch_wardn_hub_skill_audit(*args, **kwargs):
        return {
            "audit": {
                "status": "pass",
                "riskLevel": "low",
                "score": 100,
                "rank": "S",
                "summary": "No known threat patterns.",
            }
        }

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service.repository, "list_agents", list_agents)
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(
        service.repository,
        "list_recent_workspace_agent_run_steps",
        list_recent_workspace_agent_run_steps,
    )
    monkeypatch.setattr(service, "fetch_wardn_hub_skill_audit", fetch_wardn_hub_skill_audit)

    response = await service.list_workspace_skills(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
    )

    find_skills = response.skills[0]
    assert find_skills.id == skills.WARDN_FIND_SKILLS_ID
    assert find_skills.installed is True
    assert find_skills.temporary is False
    assert find_skills.audit_status == "pass"
    assert find_skills.health_status == "healthy"
    assert find_skills.enabled_agent_ids == [agent.id]
    assert find_skills.permissions[-1].key == "advisory_only"
    assert response.usage_summary.enabled_agents == 1
    assert response.usage_summary.skill_events_last_7d == 1
    assert response.usage_summary.searches_last_7d == 1
    assert response.usage_summary.skill_runs_last_7d == 1
    assert response.agents[0].calls_last_7d == 1
    assert response.agents[0].searches_last_7d == 1
    assert response.agents[0].recent_run_id == agent_run.id
    assert response.recent_activity[0].agent_run_id == agent_run.id
    assert response.recent_activity[0].event_type == "search"
    assert response.recent_activity[0].query == "kubernetes ops"
    assert response.recent_activity[0].result_count == 1
    assert response.recommendations[0].id == "kubernetes-ops"
    assert response.recommendations[0].connection_names == [
        "io.github.example/rancher-kubernetes (rancher-qa)"
    ]
    assert {workflow.id for workflow in response.guided_workflows} >= {
        "kubernetes-ops",
        "email-triage",
        "gsc-checks",
        "github-reviews",
    }


@pytest.mark.asyncio
async def test_approve_workspace_skill_persists_audited_hub_skill(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-4o-mini",
        skill_ids=[],
        is_active=True,
    )
    admin_checks = 0
    assigned_agents: list[Agent] = []

    async def require_workspace_admin(*args, **kwargs):
        nonlocal admin_checks
        admin_checks += 1

    async def get_workspace_approved_skill_by_skill_id(*args, **kwargs):
        assert kwargs["skill_id"] == "owner/repo/kubernetes-ops"
        return None

    async def get_wardn_hub_skill(arguments):
        assert arguments == {"skillId": "owner/repo/kubernetes-ops"}
        return {
            "id": "owner/repo/kubernetes-ops",
            "name": "Kubernetes ops",
            "description": "Operate clusters safely.",
            "url": "https://hub.wardnai.dev/skills/owner/repo/kubernetes-ops",
            "hash": "abc123",
            "audit": {
                "status": "pass",
                "riskLevel": "low",
                "score": 99,
                "rank": "A",
                "summary": "Looks safe.",
            },
            "source": "owner/repo",
            "sourceOwner": "owner",
            "sourceName": "repo",
            "sourceUrl": "https://github.com/owner/repo",
            "files": [{"path": "SKILL.md", "bytes": 120}],
        }

    async def list_active_workspace_agents(*args, **kwargs):
        assert kwargs["organization_id"] == organization_id
        assert kwargs["workspace_id"] == workspace_id
        return [agent]

    async def replace_workspace_approved_skill_assignments(*args, **kwargs):
        assigned_agents.extend(kwargs["agents"])

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(
        service.repository,
        "get_workspace_approved_skill_by_skill_id",
        get_workspace_approved_skill_by_skill_id,
    )
    monkeypatch.setattr(service, "get_wardn_hub_skill", get_wardn_hub_skill)
    monkeypatch.setattr(
        service.repository,
        "list_active_workspace_agents",
        list_active_workspace_agents,
    )
    monkeypatch.setattr(
        service.repository,
        "replace_workspace_approved_skill_assignments",
        replace_workspace_approved_skill_assignments,
    )

    session = FakeSession()
    response = await service.approve_workspace_skill(
        session,
        user,
        organization_id,
        workspace_id,
        WorkspaceSkillApproveRequest(skillId="owner/repo/kubernetes-ops"),
    )

    assert admin_checks == 1
    approved = session.added[0]
    assert isinstance(approved, WorkspaceApprovedSkill)
    assert approved.skill_id == "owner/repo/kubernetes-ops"
    assert approved.audit_status == "pass"
    assert approved.content_hash == "abc123"
    assert approved.approved_by_id == user.id
    assert response.skill_id == "owner/repo/kubernetes-ops"
    assert response.name == "Kubernetes ops"
    assert agent.skill_ids == [skills.WARDN_FIND_SKILLS_ID]
    assert assigned_agents == [agent]
    assert response.assigned_agent_ids == [agent.id]


@pytest.mark.asyncio
async def test_agent_approved_skill_context_loads_workspace_library_without_agent_binding(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-4o-mini",
        skill_ids=[],
        is_active=True,
    )
    workspace_skill = WorkspaceApprovedSkill(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        approved_by_id=uuid4(),
        skill_id="owner/repo/kubernetes-ops",
        name="Kubernetes ops",
        description="Operate clusters safely.",
        url="https://hub.wardnai.dev/skills/owner/repo/kubernetes-ops",
        source="owner/repo",
        source_url="https://github.com/owner/repo",
        source_owner="owner",
        source_name="repo",
        audit_status="pass",
        audit_score=99,
        audit_rank="A",
        audit_summary="Looks safe.",
        content_hash="abc123",
        status="active",
        metadata_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def list_agent_approved_skills(*args, **kwargs):
        assert kwargs["agent_id"] == agent.id
        return [workspace_skill]

    monkeypatch.setattr(
        chat_orchestrator.repository,
        "list_agent_approved_skills",
        list_agent_approved_skills,
    )

    context = await chat_orchestrator.agent_approved_skill_context(
        session_factory=fake_session_factory(FakeSession()),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
    )

    assert context[0]["skillId"] == "owner/repo/kubernetes-ops"
    assert context[0]["name"] == "Kubernetes ops"


@pytest.mark.asyncio
async def test_assign_workspace_skill_agents_enables_gateway(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    workspace_skill = WorkspaceApprovedSkill(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        approved_by_id=user.id,
        skill_id="owner/repo/kubernetes-ops",
        name="Kubernetes ops",
        description="Operate clusters safely.",
        url="https://hub.wardnai.dev/skills/owner/repo/kubernetes-ops",
        source="owner/repo",
        source_url="https://github.com/owner/repo",
        source_owner="owner",
        source_name="repo",
        audit_status="pass",
        audit_score=99,
        audit_rank="A",
        audit_summary="Looks safe.",
        content_hash="abc123",
        status="active",
        metadata_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Ops agent",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-4o-mini",
        skill_ids=[],
        is_active=True,
    )
    assigned_agents: list[Agent] = []

    async def require_workspace_admin(*args, **kwargs):
        return None

    async def get_workspace_approved_skill(*args, **kwargs):
        assert kwargs["workspace_skill_id"] == workspace_skill.id
        return workspace_skill

    async def get_agent(*args, **kwargs):
        assert kwargs["agent_id"] == agent.id
        return agent

    async def replace_workspace_approved_skill_assignments(*args, **kwargs):
        assigned_agents.extend(kwargs["agents"])

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(
        service.repository,
        "get_workspace_approved_skill",
        get_workspace_approved_skill,
    )
    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(
        service.repository,
        "replace_workspace_approved_skill_assignments",
        replace_workspace_approved_skill_assignments,
    )

    response = await service.assign_workspace_skill_agents(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
        workspace_skill.id,
        WorkspaceSkillAgentAssignmentRequest(agentIds=[agent.id]),
    )

    assert assigned_agents == [agent]
    assert agent.skill_ids == [skills.WARDN_FIND_SKILLS_ID]
    assert response.assigned_agent_ids == [agent.id]


@pytest.mark.asyncio
async def test_search_agent_skills_returns_approved_matches_before_hub(monkeypatch) -> None:
    async def search_wardn_hub_skills(arguments):
        raise AssertionError("Hub fallback should not run when approved skills match")

    monkeypatch.setattr(skills, "search_wardn_hub_skills", search_wardn_hub_skills)

    response = await skills.search_agent_skills(
        {"query": "kubernetes ops", "limit": 8},
        approved_skills=[
            {
                "workspaceSkillId": str(uuid4()),
                "skillId": "owner/repo/kubernetes-ops",
                "name": "Kubernetes ops",
                "description": "Operate Kubernetes clusters safely.",
                "source": "owner/repo",
                "auditStatus": "pass",
            }
        ],
    )

    assert response["scope"] == "workspace_library"
    assert response["fallback"] is False
    assert response["approvedResultCount"] == 1
    assert response["results"][0]["approved"] is True
    assert response["results"][0]["temporary"] is False


@pytest.mark.asyncio
async def test_update_agent_skills_toggles_find_skills(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-4o-mini",
        skill_ids=[],
        is_active=True,
    )
    admin_checks = 0

    async def require_workspace_admin(*args, **kwargs):
        nonlocal admin_checks
        admin_checks += 1

    async def get_agent(*args, **kwargs):
        assert kwargs["agent_id"] == agent.id
        assert kwargs["workspace_id"] == workspace_id
        return agent

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_agent", get_agent)

    response = await service.update_agent_skills(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
        agent.id,
        AgentSkillUpdateRequest(skillIds=[skills.WARDN_FIND_SKILLS_ID]),
    )

    assert admin_checks == 1
    assert agent.skill_ids == [skills.WARDN_FIND_SKILLS_ID]
    assert response.enabled_skill_ids == [skills.WARDN_FIND_SKILLS_ID]
    assert response.available_skill_count == 1


@pytest.mark.asyncio
async def test_search_workspace_skills_returns_temporary_guidance(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)

    async def require_workspace_member(*args, **kwargs):
        return None, None, None

    async def search_wardn_hub_skills(arguments):
        assert arguments == {"query": "github review", "limit": 3}
        return {
            "query": "github review",
            "count": 1,
            "results": [
                {
                    "id": "owner/repo/github-review",
                    "name": "github-review",
                    "description": "Review PRs safely.",
                    "url": "https://hub.wardnai.dev/skills/owner/repo/github-review",
                    "source": "owner/repo",
                    "sourceOwner": "owner",
                    "sourceName": "repo",
                    "isOfficial": False,
                    "installs": 5,
                    "auditStatus": "pass",
                    "auditScore": 98,
                    "auditRank": "A",
                }
            ],
        }

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service, "search_wardn_hub_skills", search_wardn_hub_skills)

    response = await service.search_workspace_skills(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
        query="github review",
        limit=3,
    )

    result = response.results[0]
    assert result.id == "owner/repo/github-review"
    assert result.temporary is True
    assert result.installed is False
    assert result.permissions[-1].key == "advisory_only"


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
