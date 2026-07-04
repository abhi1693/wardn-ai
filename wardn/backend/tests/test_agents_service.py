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
    WorkspaceConversation,
)
from app.modules.agents.schemas import AgentChatMessage, AgentCreate, AgentToolAssignmentUpdate
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.schemas import LLMProviderModelListResponse, LLMProviderModelRead
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
            status="completed",
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
            session,
            conversation,
            provider_stream(),
        )
    ]
    chunks = ui_stream_chunks(raw_chunks)

    assert [chunk["type"] for chunk in chunks] == [
        "start",
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
        "status": "completed",
    }
    assert chunks[4]["delta"] == "Final answer"
    assert persisted == [
        {
            "conversation_id": conversation.id,
            "role": "assistant",
            "content": "Final answer",
            "parts": [
                {
                    "type": "data-tool-activity",
                    "id": "tool-call-1",
                    "data": {
                        "toolName": "resolve-library-id",
                        "status": "completed",
                    },
                },
                {"type": "text", "text": "Final answer"},
            ],
        }
    ]
    assert session.commits == 1


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
    assert service.CODEX_COMPAT_VERSION == "0.142.0"
    assert service.CODEX_COMPAT_USER_AGENT.startswith("codex_cli_rs/0.142.0 ")


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
    assert session.commits == 1


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
